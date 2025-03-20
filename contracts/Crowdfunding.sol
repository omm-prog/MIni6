// SPDX-License-Identifier: MIT
pragma solidity ^0.8.19;

contract Crowdfunding {
    address public admin;
    uint256 public campaignCount;
    bool public paused;

    enum CampaignState { Active, Successful, Failed }

    struct Campaign {
        string name;
        string description;
        uint256 goal;
        uint256 deadline;
        address payable owner;
        CampaignState state;
        uint256 balance;
        bool proofSubmitted;
    }

    struct Backer {
        uint256 amountContributed;
    }

    mapping(uint256 => Campaign) public campaigns;
    mapping(uint256 => mapping(address => Backer)) public campaignBackers;
    mapping(uint256 => address[]) private campaignContributors;
    mapping(address => uint256[]) public userCampaigns;

    event CampaignCreated(uint256 campaignId, address owner, string name, uint256 goal, uint256 deadline);
    event ContributionReceived(uint256 campaignId, address contributor, uint256 amount);
    event CampaignSuccessful(uint256 campaignId);
    event CampaignFailed(uint256 campaignId);
    event FundsWithdrawn(uint256 campaignId, uint256 amount);
    event RefundIssued(uint256 campaignId, address backer, uint256 amount);
    event CampaignPaused(bool isPaused);

    modifier onlyAdmin() {
        require(msg.sender == admin, "Only admin can call this function");
        _;
    }

    modifier onlyOwner(uint256 _campaignId) {
        require(msg.sender == campaigns[_campaignId].owner, "Not the campaign owner");
        _;
    }

    modifier campaignActive(uint256 _campaignId) {
        require(campaigns[_campaignId].state == CampaignState.Active, "Campaign is not active");
        require(block.timestamp < campaigns[_campaignId].deadline, "Campaign deadline passed");
        _;
    }

    modifier contractNotPaused() {
        require(!paused, "Contract is paused");
        _;
    }

    constructor() {
        admin = msg.sender;
        paused = false;
    }

    function createCampaign(
        string memory _name,
        string memory _description,
        uint256 _goal,
        uint256 _duration
    ) external contractNotPaused {
        require(_goal > 0, "Goal must be greater than 0");
        require(_duration > 0, "Duration must be greater than 0");

        uint256 campaignId = campaignCount++;

        campaigns[campaignId] = Campaign({
            name: _name,
            description: _description,
            goal: _goal,
            deadline: block.timestamp + (_duration * 1 days),
            owner: payable(msg.sender),
            state: CampaignState.Active,
            balance: 0,
            proofSubmitted: false
        });

        userCampaigns[msg.sender].push(campaignId);

        emit CampaignCreated(campaignId, msg.sender, _name, _goal, block.timestamp + (_duration * 1 days));
    }

    function contribute(uint256 _campaignId)
        external
        payable
        campaignActive(_campaignId)
        contractNotPaused
    {
        require(msg.value >= 0.01 ether, "Minimum contribution is 0.01 ETH");

        Campaign storage campaign = campaigns[_campaignId];

        if (campaignBackers[_campaignId][msg.sender].amountContributed == 0) {
            campaignContributors[_campaignId].push(msg.sender);
        }

        campaignBackers[_campaignId][msg.sender].amountContributed += msg.value;
        campaign.balance += msg.value;

        if (campaign.balance >= campaign.goal) {
            campaign.state = CampaignState.Successful;
            emit CampaignSuccessful(_campaignId);
        }

        emit ContributionReceived(_campaignId, msg.sender, msg.value);
    }

    // 🔹 Now both Admin and Campaign Owner can submit proof
    function submitCompletionProof(uint256 _campaignId) external {
        require(
            msg.sender == admin || msg.sender == campaigns[_campaignId].owner,
            "Not authorized"
        );

        Campaign storage campaign = campaigns[_campaignId];

        require(campaign.state == CampaignState.Successful, "Campaign is not successful");
        require(!campaign.proofSubmitted, "Proof already submitted");

        campaign.proofSubmitted = true;
    }

    function withdrawFunds(uint256 _campaignId) external onlyOwner(_campaignId) {
        Campaign storage campaign = campaigns[_campaignId];
        require(campaign.state == CampaignState.Successful, "Campaign is not successful");
        require(campaign.proofSubmitted, "Completion proof not submitted");
        require(campaign.balance > 0, "No funds to withdraw");

        uint256 amount = campaign.balance;
        campaign.balance = 0;
        campaign.owner.transfer(amount);

        emit FundsWithdrawn(_campaignId, amount);
    }

    function refundBackers(uint256 _campaignId) external {
        Campaign storage campaign = campaigns[_campaignId];
        require(campaign.state == CampaignState.Failed, "Campaign not failed");

        uint256 amount = campaignBackers[_campaignId][msg.sender].amountContributed;
        require(amount > 0, "You didn't contribute to this campaign");

        campaignBackers[_campaignId][msg.sender].amountContributed = 0;
        campaign.balance -= amount;
        payable(msg.sender).transfer(amount);

        emit RefundIssued(_campaignId, msg.sender, amount);
    }

    function autoRefund(uint256 _campaignId) external {
        Campaign storage campaign = campaigns[_campaignId];

        require(block.timestamp > campaign.deadline, "Campaign deadline not passed");
        require(!campaign.proofSubmitted, "Proof already submitted");
        require(campaign.state == CampaignState.Successful, "Campaign is not successful");

        campaign.state = CampaignState.Failed;

        // Refund all contributors
        for (uint256 i = 0; i < campaignContributors[_campaignId].length; i++) {
            address backer = campaignContributors[_campaignId][i];
            uint256 amount = campaignBackers[_campaignId][backer].amountContributed;

            if (amount > 0) {
                campaignBackers[_campaignId][backer].amountContributed = 0;
                campaign.balance -= amount;
                payable(backer).transfer(amount);

                emit RefundIssued(_campaignId, backer, amount);
            }
        }

        emit CampaignFailed(_campaignId);
    }

    function getContributors(uint256 _campaignId) external view returns (address[] memory, uint256[] memory) {
        uint256 length = campaignContributors[_campaignId].length;
        address[] memory contributors = new address[](length);
        uint256[] memory amounts = new uint256[](length);

        for (uint256 i = 0; i < length; i++) {
            address contributor = campaignContributors[_campaignId][i];
            contributors[i] = contributor;
            amounts[i] = campaignBackers[_campaignId][contributor].amountContributed;
        }

        return (contributors, amounts);
    }

    function togglePause() external onlyAdmin {
        paused = !paused;
        emit CampaignPaused(paused);
    }

    function getMyCampaigns() external view returns (uint256[] memory) {
        return userCampaigns[msg.sender];
    }
}

